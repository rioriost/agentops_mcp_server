class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/df/4a/d4692c74ae45ee4af6db8c317deaaed7ff687f5464db4f3c1e12ddcf3266/agentops_mcp_server-0.2.2.tar.gz"
  sha256 "cffba1d7aad5659b2b0ae116872cadec073c4e38d1281e42d28bfb45db8fa2d5"
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
