class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/9f/90/b2543700c2730ffe6d9cafa393ede589bf00449cb65e767b983f3c834a97/agentops_mcp_server-0.4.7.tar.gz"
  sha256 "4a6b29d6559c325379789753486f24c900481b7e74b6e40e2f171a719d17df5c"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
    prefix.install "README-jp.md"
    prefix.install "docs"
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
