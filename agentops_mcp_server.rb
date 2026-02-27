class AgentopsMcpServer < Formula
  include Language::Python::Virtualenv

  desc "AgentOps MCP Server"
  homepage "https://github.com/rioriost/homebrew-agentops_mcp_server/"
  url "https://files.pythonhosted.org/packages/0c/46/0183bc47dbd066606328aba358190bc753cdfaff1f3aac24653acaf956f5/agentops_mcp_server-0.0.11.tar.gz"
  sha256 "ff030ef997f5a5d9c25d4a7bae4f85be4595de37d4d42788ab6f763ef7d143ec"
  license "MIT"

  depends_on "python@3.14"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/agentops_mcp_server", "--help"
  end
end
