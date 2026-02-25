class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/82/49/9f30d9bd3eb66f7c77f6c89b8ca4b8e46ea02b7e786d6a3a7241dc1fafde/agentops_mcp_server-0.0.4.tar.gz"
  sha256 "3479dc192c22be2563fad776d9c6a871af790b76d7dc03910a91db5a503dd954"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
